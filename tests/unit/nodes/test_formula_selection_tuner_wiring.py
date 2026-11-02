"""Formula selection must reach every tuner consumer, and nothing else may change.

Issue #1294 / PR #1377. A ``weighted_sum`` formula gives a composed run an
EFFECTIVE metric (``evaluation.weighted_sum.v1.<sha>``, higher is better) that
ranks candidates, while the SOURCE metric keeps its own units for Health. The
aggregation arithmetic is covered in ``tests/unit/execute_tools``. These tests
cover the tuner's wiring: each one goes through a production boundary that a
one-line regression could disconnect from the formula, and says which
assertion fails when that happens.

The composition is real: the synthetic masked-regression pack (source
``masked_mse``, LOWER; secondary ``masked_mae``, LOWER), relocated under
``tmp_path`` with an ``evaluation`` section added. A LOWER source is chosen on
purpose. Its ordering is the reverse of the effective utility's ordering, so a
consumer that falls back to the source metric picks the other candidate:

```text
candidate   masked_mse  masked_mae   utility = (3*(1-mse) + 1*(1-mae/10)) / 4
A           0.2         2.0          0.8     <- formula winner
B           0.1         10.0         0.675   <- source-metric winner (lower mse)
```

Nothing here touches a GPU, a provider or a real scoring subprocess.
"""

from __future__ import annotations

import importlib
import json
import shutil
import textwrap
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.training_diagnosis import TrainingDiagnosis
from execute_tools.evaluation_child import (
    EvaluationNotScoreableError,
    aggregate_child_outcome,
    scoring_refusal_fields,
)
from execute_tools.evaluation_metric import MetricResult, NotScoreableResult
from execute_tools.evaluation_results import EvaluationEvidence, EvaluationTransportError
from execute_tools.health_checks.config import (
    default_health_policy_path,
    materialize_effective_config,
)
from execute_tools.health_checks.registry import _REGISTRY
from execute_tools.health_checks.schemas import PerSampleEvidence
from execute_tools.metric_order import MetricOrder
from execute_tools.training_history import TrainingResults
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AdmissionOutcome,
    AttemptExecution,
    AttemptIdentity,
    RunBindings,
    RunExitSnapshot,
    TrainingOutcome,
)
from tests.helpers.run_seed import TEST_RUN_SEED
from tests.helpers.tuner_composed_fixture import _isolated_registrations
from workflows.evaluation_composition import compose_evaluation
from workflows.evaluation_selection import selection_binding
from workflows.task_composition import (
    RunTaskComposition,
    bind_run_task_composition,
    build_task_composition_ref,
    compose_run_task_bindings,
)

# The tuner package rebinds ``sys.modules`` to its main module, so private
# submodules are reached by dotted path (the repository convention).
tuner = importlib.import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")
execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")
planning = importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")
policy = importlib.import_module("nodes.ml_hyperparameter_tune_agent.policy")
records = importlib.import_module("nodes.ml_hyperparameter_tune_agent.records")
round_health = importlib.import_module("nodes.ml_hyperparameter_tune_agent.round_health")
scoring_transport = importlib.import_module("nodes.ml_hyperparameter_tune_agent.scoring_transport")

ROOT = Path(__file__).resolve().parents[3]
MASKED_MANIFEST = ROOT / "configs" / "task_composition" / "synthetic_masked_regression.yaml"
MODEL_TYPE = "masked_reference_mlp"

FORMULA: dict[str, Any] = {
    "components": [
        {"kind": "metric", "id": "mse", "metric": "masked_mse", "meaning": "Masked MSE"},
        {"kind": "metric", "id": "mae", "metric": "masked_mae", "meaning": "Masked MAE"},
    ],
    "selection": {
        "kind": "formula",
        "formula": {
            "family": "weighted_sum",
            "params": {
                "terms": [
                    {
                        "component": "mse",
                        "weight": 3.0,
                        "lower": 0.0,
                        "upper": 1.0,
                        "out_of_range": "refuse",
                    },
                    {
                        "component": "mae",
                        "weight": 1.0,
                        "lower": 0.0,
                        "upper": 10.0,
                        "out_of_range": "refuse",
                    },
                ]
            },
        },
    },
}


class _StopBeforeEffects(BaseException):
    """Raised by test doubles; ``BaseException`` escapes the tuner's handlers."""


# --------------------------------------------------------------------------
# Fixtures: a real masked-regression composition, with and without a formula
# --------------------------------------------------------------------------


def _masked_manifest(tmp_path: Path, evaluation: dict[str, Any] | None) -> Path:
    """Relocate the masked pack; its relative references stay valid."""
    raw = yaml.safe_load(MASKED_MANIFEST.read_text(encoding="utf-8"))
    if evaluation is not None:
        raw["evaluation"] = evaluation
    shutil.copytree(
        ROOT / "examples" / "synthetic_masked_regression",
        tmp_path / "examples" / "synthetic_masked_regression",
    )
    target = tmp_path / "configs" / "task_composition" / "manifest.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    return target


@pytest.fixture
def compose(tmp_path: Path) -> Iterator[Any]:
    """Compose the masked pack (formula or plain) under isolated registrations."""
    with _isolated_registrations():

        def _compose(evaluation: dict[str, Any] | None = FORMULA) -> RunTaskComposition:
            root = tmp_path / ("formula_pack" if evaluation is not None else "plain_pack")
            return compose_run_task_bindings(str(_masked_manifest(root, evaluation)))

        yield _compose


def _effective_id(composition: RunTaskComposition) -> str:
    binding = composition.selection_binding
    assert binding is not None
    return binding.effective_metric.id


def _tuner_input(tmp_path: Path, composition: RunTaskComposition, **overrides: Any):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return HyperparamTuningInput(
        model_type=MODEL_TYPE,
        run_seed=TEST_RUN_SEED,
        planner_strategy="native-timing-v1",
        is_trial=True,
        llm_provider="openai",
        llm_model_id="gpt-5-mini",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(workspace), run_name="formula"),
        ),
        task_composition_ref=build_task_composition_ref(composition),
        **overrides,
    )


def _child_results(composition: RunTaskComposition, mse: float, mae: float) -> dict[str, Any]:
    """The scoring child's ``--output_json`` payload, built by its own producer.

    ``aggregate_child_outcome`` is what ``denoising_score_single`` calls; the
    dict mirrors that child's ``_emit_outcome`` success payload.
    """
    outcome, secondaries = aggregate_child_outcome(
        composition,
        MetricResult(metric_id="masked_mse", direction="lower", scalar=mse, per_sample=[mse, mse]),
        {
            "secondary_metric_results": [
                MetricResult(metric_id="masked_mae", direction="lower", scalar=mae).model_dump(
                    mode="json"
                )
            ]
        },
    )
    assert isinstance(outcome, MetricResult)
    return {
        "denoising_score": outcome.scalar,
        "file_vector": outcome.per_sample,
        "metric_result": outcome.model_dump(mode="json", exclude={"per_sample"}),
        **secondaries,
    }


def _bindings(agent_input: HyperparamTuningInput, **overrides: Any) -> SimpleNamespace:
    return SimpleNamespace(agent_input=agent_input, **overrides)


# --------------------------------------------------------------------------
# Parent-side verification of the child envelope (adopt_child_score)
# --------------------------------------------------------------------------


def _tamper_aggregate(good: dict[str, Any], _other: dict[str, Any]) -> dict[str, Any]:
    """The effective scalar is consistently raised everywhere except in the terms."""
    bad = json.loads(json.dumps(good))
    bad["evaluation_result"]["aggregate"] = 0.9
    bad["metric_result"]["scalar"] = 0.9
    bad["denoising_score"] = 0.9
    return bad


def _tamper_derived_terms(good: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Raw value kept; normalized/utility/contribution and aggregate from mse=0.1."""
    bad = json.loads(json.dumps(other))
    bad["evaluation_result"]["components"][0]["raw"] = good["evaluation_result"]["components"][0][
        "raw"
    ]
    bad["evaluation_result"]["source_metric_result"] = good["evaluation_result"][
        "source_metric_result"
    ]
    return bad


def _tamper_raw_value(good: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Self-consistent terms for mse=0.1 beside a source result that says 0.2."""
    bad = json.loads(json.dumps(other))
    bad["evaluation_result"]["source_metric_result"] = good["evaluation_result"][
        "source_metric_result"
    ]
    return bad


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (_tamper_aggregate, "aggregate disagrees with its components"),
        (_tamper_derived_terms, "disagrees with recomputed arithmetic"),
        (_tamper_raw_value, "raw value disagrees with its source result"),
    ],
    ids=["aggregate", "derived-terms", "raw-vs-source"],
)
def test_adopt_child_score_recomputes_formula_evidence(compose, tmp_path, tamper, message):
    """Defect: the parent adopts a child's utility on trust.

    If ``adopt_child_score`` stops calling ``validate_child_evaluation``, every
    tampered envelope is adopted with its inflated scalar and the
    ``pytest.raises`` below fails. The untampered envelope must still be adopted
    as 0.8, so the refusal is not a blanket rejection of formula payloads.
    """
    composition = compose()
    bindings = _bindings(_tuner_input(tmp_path, composition))
    good = _child_results(composition, mse=0.2, mae=2.0)
    other = _child_results(composition, mse=0.1, mae=2.0)

    adopted = scoring_transport.adopt_child_score(
        bindings,
        {"status": "success", "results": good},
        execution._require_successful_scoring_result,
    )
    assert adopted.scalar == 0.8

    with pytest.raises(EvaluationTransportError, match=message):
        scoring_transport.adopt_child_score(
            bindings,
            {"status": "success", "results": tamper(good, other)},
            execution._require_successful_scoring_result,
        )


def test_crashed_formula_scorer_keeps_its_infrastructure_status(compose, tmp_path):
    """Defect: a crashed scorer under a formula is misreported as bad evidence.

    The OOM-killed child leaves only the parent's pre-created ``{}`` output, so
    the sandbox envelope carries a status and stderr and no results. Validating
    evidence first would raise ``EvaluationTransportError`` ("omitted formula
    evaluation evidence") and lose ``oom_host_ram`` and the stderr text.
    """
    composition = compose()
    bindings = _bindings(_tuner_input(tmp_path, composition))
    output_json = tmp_path / "score.json"
    output_json.write_text("{}", encoding="utf-8")
    envelope = {
        "status": "oom_host_ram",
        "message": "Scoring killed: host RAM exhausted (stderr tail)",
        **scoring_refusal_fields(str(output_json)),
    }

    with pytest.raises(execution.ScoringSkillExecutionError) as error:
        scoring_transport.adopt_child_score(
            bindings, envelope, execution._require_successful_scoring_result
        )
    assert "status='oom_host_ram'" in str(error.value)
    assert "host RAM exhausted (stderr tail)" in str(error.value)


def test_structured_formula_refusal_becomes_typed_not_scoreable(compose, tmp_path):
    """Defect: an out-of-range component refusal turns into a generic scorer error.

    The child exits 1 after writing its refusal and component evidence; the
    sandbox recovers them through ``scoring_refusal_fields``. The parent must
    raise ``EvaluationNotScoreableError`` carrying that evidence. Skipping the
    refusal inspection would raise ``ScoringSkillExecutionError`` instead.
    """
    composition = compose()
    bindings = _bindings(_tuner_input(tmp_path, composition))
    refusal, secondaries = aggregate_child_outcome(
        composition,
        MetricResult(metric_id="masked_mse", direction="lower", scalar=2.0),
        {
            "secondary_metric_results": [
                MetricResult(metric_id="masked_mae", direction="lower", scalar=2.0).model_dump(
                    mode="json"
                )
            ]
        },
    )
    assert isinstance(refusal, NotScoreableResult)
    output_json = tmp_path / "score.json"
    output_json.write_text(
        json.dumps(
            {
                "denoising_score": None,
                "file_vector": None,
                "not_scoreable": refusal.model_dump(mode="json"),
                **secondaries,
            }
        ),
        encoding="utf-8",
    )
    envelope = {
        "status": "error",
        "message": "Deliverable not scoreable",
        **scoring_refusal_fields(str(output_json)),
    }

    with pytest.raises(EvaluationNotScoreableError) as error:
        scoring_transport.adopt_child_score(
            bindings, envelope, execution._require_successful_scoring_result
        )
    evidence = error.value.evaluation_result
    assert evidence.aggregate is None
    assert [f.requirement for f in evidence.failures] == ["mse"]


# --------------------------------------------------------------------------
# Round Health reads the SOURCE metric, never the utility (apply_round_health)
# --------------------------------------------------------------------------

_SOURCE_FLOOR_PLUGIN = '''
from typing import ClassVar

from execute_tools.health_checks import register
from execute_tools.health_checks.schemas import CheckInputDeclaration, HealthCheckResult


class SourceScoreFloor:
    """Pass only when the round's score is at least 0.5 (a source-unit threshold)."""

    name: ClassVar[str] = "formula_fixture_source_floor"
    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        consumes_view="formula_fixture.none",
    )

    def __init__(self):
        self.seen = []

    def run(self, ctx, config=None):
        self.seen.append((ctx.denoising_score, list(ctx.file_vector), ctx.per_sample_evidence))
        passed = ctx.denoising_score is not None and ctx.denoising_score >= 0.5
        return HealthCheckResult(check_name=self.name, passed=passed, reason="source floor 0.5")


register(SourceScoreFloor())
'''


def _source_floor_health(root: Path) -> str:
    (root / "source_floor.py").write_text(_SOURCE_FLOOR_PLUGIN, encoding="utf-8")
    config = root / "task_health.yaml"
    config.write_text(
        textwrap.dedent(
            """
            facts:
              encoding_family: formula_fixture
            plugins:
              - kind: file
                ref: source_floor.py
            roster:
              - gate_id: formula_fixture_source_floor
                check: formula_fixture_source_floor
                disposition: blocking
                reason: Source-unit floor for the formula Health witness.
            """
        ),
        encoding="utf-8",
    )
    return str(config)


def _higher_source_formula_evidence() -> tuple[float, dict[str, Any]]:
    """Source accuracy 0.2 (per-sample 0.1, 0.3) whose utility is 0.8.

    Utility = (1*0.2 + 3*(1 - 0/10)) / 4 = 0.8: good-looking utility, poor source.
    """
    from execute_tools.evaluation_aggregation import aggregate_evaluation
    from tests.helpers.metric_fixtures import accuracy_like_spec

    accuracy = accuracy_like_spec("accuracy")
    error = accuracy_like_spec("error").model_copy(update={"direction": "lower"})
    spec = {
        "components": [
            {"kind": "metric", "id": "quality", "metric": "accuracy", "meaning": "Accuracy"},
            {"kind": "metric", "id": "error", "metric": "error", "meaning": "Error"},
        ],
        "selection": {
            "kind": "formula",
            "formula": {
                "family": "weighted_sum",
                "params": {
                    "terms": [
                        {
                            "component": "quality",
                            "weight": 1.0,
                            "lower": 0.0,
                            "upper": 1.0,
                            "out_of_range": "refuse",
                        },
                        {
                            "component": "error",
                            "weight": 3.0,
                            "lower": 0.0,
                            "upper": 10.0,
                            "out_of_range": "refuse",
                        },
                    ]
                },
            },
        },
    }
    evaluation = compose_evaluation(
        {"evaluation": spec}, ".", {"accuracy": accuracy, "error": error}, None
    )
    assert evaluation is not None
    outcome, evidence = aggregate_evaluation(
        evaluation,
        accuracy,
        MetricResult(metric_id="accuracy", direction="higher", scalar=0.2, per_sample=[0.1, 0.3]),
        [MetricResult(metric_id="error", direction="lower", scalar=0.0)],
    )
    assert isinstance(outcome, MetricResult) and outcome.scalar == 0.8
    return outcome.scalar, evidence.model_dump(mode="json")


def test_round_health_judges_formula_rounds_on_the_source_score(tmp_path):
    """Defect: task Health thresholds are compared with the formula utility.

    The production round boundary is handed the adopted scalar, which under a
    formula is the utility (0.8). A source-unit floor of 0.5 must still see the
    source accuracy 0.2 and its per-sample vector and reject the round. If
    ``apply_round_health`` forwards its kwargs unchanged, the check sees 0.8 and
    an empty vector, passes, and ``is_degenerate`` stays False.
    """
    utility, evidence = _higher_source_formula_evidence()
    with _isolated_registrations():
        binding = _source_floor_health(tmp_path)
        effective_path, _ = materialize_effective_config(
            default_health_policy_path(), None, str(tmp_path), task_health_binding=binding
        )
        score_res: dict[str, Any] = {
            "status": "success",
            "results": {"denoising_score": utility, "evaluation_result": evidence},
        }
        outcome = round_health.apply_round_health(
            score_res,
            merge_score_validity=policy._merge_score_validity_failure,
            enabled=True,
            round_index=1,
            config_path=effective_path,
            production_config_path=default_health_policy_path(),
            task_health_binding=binding,
            healthgate_mode="blocking",
            result_authority="scientific",
            model_name=MODEL_TYPE,
            run_name="formula",
            exp_id="e1",
            models_dir=None,
            denoised_filename_fn=lambda i: str(tmp_path / f"deliverable_{i}"),
            target_path_fn=lambda i: str(tmp_path / f"target_{i}"),
            file_vector=[],
            denoising_score=utility,
            per_sample_evidence=PerSampleEvidence.SCALAR_ONLY,
            gate_results_to_score_meta=policy._gate_results_to_score_meta,
        )
        check = _REGISTRY["formula_fixture_source_floor"]
        seen = list(check.seen)

    assert outcome.evaluated
    assert seen == [(0.2, [0.1, 0.3], PerSampleEvidence.for_per_sample([0.1, 0.3]))]
    assert score_res["results"]["is_degenerate"] is True
    assert [row["check_passed"] for row in score_res["results"]["health_gate_results"]] == [False]


# --------------------------------------------------------------------------
# Records and run output carry the formula identity (records.py)
# --------------------------------------------------------------------------


def _run_bindings(
    agent_input: HyperparamTuningInput,
    composition: RunTaskComposition,
    *,
    summary: list[dict[str, Any]] | None = None,
) -> RunBindings:
    binding = composition.selection_binding
    order_spec = binding.effective_metric if binding else composition.metric.spec
    local = agent_input.storage.local
    assert local is not None
    return RunBindings(
        agent_input=agent_input,
        sandbox=SimpleNamespace(get_summary=lambda: list(summary or [])),
        brain=None,
        custom_loss_inventory=None,
        run_profile=None,
        run_model_io=None,
        run_deliverable_spec=None,
        run_metric=composition.metric,
        run_secondary_metrics=(),
        run_order=MetricOrder(order_spec),
        run_task_render=None,
        run_name=local.run_name,
        workspace=local.workspace,
        file_index=0,
        max_rounds=1,
        model_type_setting=MODEL_TYPE,
        trial_allowed=True,
        resolved_data_scope=[0],
        scope_is_partial=False,
        expert_advice_str="",
        config_manual_data=None,
        model_description=None,
        trial_vram_budget=None,
        formal_vram_budget=None,
        trial_time_budget=None,
        formal_time_budget=None,
        attempts_per_round_setting=1,
        attempts_per_formal_round_setting=1,
        max_fail_rounds_setting=1,
        formal_reference_score=None,
        formal_reference_source=None,
        resolved_skip_formal_threshold=None,
        resolved_bypass_formal_threshold=None,
        hardware_context=None,
        device_identity=None,
        time_data_dir=local.workspace,
        anchor_map_data=None,
        reference_scores=None,
        started_at="2026-01-01 00:00:00",
        health_checks_config_source=None,
        health_config_sha256=None,
        run_scientific_gate_ids=frozenset(),
        selection_binding=binding,
    )


def _built_record(bindings: RunBindings, score_results: dict[str, Any]) -> dict[str, Any]:
    ordering = SimpleNamespace(
        proposed_strategy=None,
        proposed_file_order=None,
        proposal_rejected=False,
        proposal_rejection_reason=None,
        override_strategy=None,
        override_file_order=None,
        resolved_strategy="sequential",
        resolved_file_order=None,
        resolution_source="default",
    )
    trial = SimpleNamespace(
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.1,
        eval_strategy="snapshot",
        eval_portion=0.1,
        train_portion=0.1,
    )
    prepared = SimpleNamespace(
        _planned_portions={},
        cfg_eval_portion=0.1,
        cfg_train_portion=0.1,
        cfg_trial_portion=0.1,
        eval_psd_segments=None,
        exp_id="e1",
        hypothesis="h",
        model_type=MODEL_TYPE,
        ordering=ordering,
        plan=SimpleNamespace(is_trial=True),
        planned_eval_strategy="snapshot",
        planned_trial_strategy="snapshot",
        record_params={},
        strategy_normalization_reason=None,
        train_psd_segments=None,
        trial_config=trial,
    )
    return records.build_attempt_record(
        bindings,
        prepared,
        AttemptIdentity(round_index=1, attempt_in_round=1, is_formal_round=False),
        AdmissionOutcome(resource_check={}),
        TrainingOutcome(
            train_status={},
            train_time=1.0,
            training_results=TrainingResults(
                legacy_payload={}, history=None, history_state="absent"
            ),
        ),
        AttemptExecution(
            inf_status={},
            inference_time=1.0,
            is_degenerate=False,
            metric_payload=score_results.get("metric_result"),
            score_results=score_results,
            scoring_time=1.0,
            train_results={},
            training_diagnosis=TrainingDiagnosis(state="absent", validation_state="absent"),
        ),
        reflection={},
    )


def test_attempt_record_persists_formula_evidence(compose, tmp_path):
    """Defect: the attempt record drops the component evidence behind its score.

    Without ``evaluation_record_fields`` the record keeps the utility in
    ``denoising_score`` but loses ``evaluation_result``, so nobody can audit the
    source value or the terms. A plain run must still write no such key.
    """
    composition = compose()
    results = _child_results(composition, mse=0.2, mae=2.0)
    record = _built_record(_run_bindings(_tuner_input(tmp_path, composition), composition), results)
    assert record["denoising_score"] == 0.8
    assert EvaluationEvidence.model_validate(record["evaluation_result"]) == (
        EvaluationEvidence.model_validate(results["evaluation_result"])
    )
    assert record["evaluation_result"]["source_metric_result"]["scalar"] == 0.2

    plain = compose(None)
    plain_record = _built_record(
        _run_bindings(_tuner_input(tmp_path, plain), plain),
        {"denoising_score": 0.2, "metric_result": None},
    )
    assert "evaluation_result" not in plain_record


@pytest.mark.parametrize("degraded", [False, True], ids=["validated", "degraded"])
def test_run_output_stamps_the_effective_metric_spec(compose, tmp_path, monkeypatch, degraded):
    """Defect: the run output tells the interpreter to rank by the source metric.

    The output's ``metric_spec`` is the interpreter's only ranking authority.
    Under a formula it must be the effective spec (higher), on both the
    validated output and the degraded partial file. Stamping
    ``run_metric.spec`` would write ``masked_mse``/lower here. A plain run keeps
    the source spec.
    """
    if degraded:

        def _boom(_payload):
            raise RuntimeError("forced serialization failure")

        monkeypatch.setattr(records, "encoded_record", _boom)

    def _stamped(composition: RunTaskComposition, run_dir: Path) -> dict[str, Any]:
        run_dir.mkdir()
        agent_input = _tuner_input(run_dir, composition)
        records.finalize_run_output(
            _run_bindings(agent_input, composition),
            RunExitSnapshot(
                completed_rounds=1,
                total_attempts=0,
                consecutive_fails=0,
                scope_violation_reason=None,
                evidence_channel_failure=None,
                skipped_formal_for_no_valid_winner=False,
                physical_rejections_buffer=[],
                last_plan=None,
            ),
        )
        payload = json.loads(
            (run_dir / "workspace" / "run_output_formula.json").read_text(encoding="utf-8")
        )
        assert ("_partial_reason" in payload) is degraded
        return payload["metric_spec"]

    composition = compose()
    formula_spec = _stamped(composition, tmp_path / "formula")
    assert formula_spec["id"] == _effective_id(composition)
    assert formula_spec["direction"] == "higher"

    plain_spec = _stamped(compose(None), tmp_path / "plain")
    assert plain_spec["id"] == "masked_mse"
    assert plain_spec["direction"] == "lower"


# --------------------------------------------------------------------------
# The planner is told the effective metric (planning._request_attempt_plan)
# --------------------------------------------------------------------------


def _planner_metric_spec(agent_input: HyperparamTuningInput, composition: RunTaskComposition):
    """Drive the production planner request with a recording brain."""
    brain = SimpleNamespace(plan=Mock(return_value={"unparsed": "decision"}))
    bindings = SimpleNamespace(
        agent_input=agent_input,
        sandbox=SimpleNamespace(get_summary=lambda: []),
        brain=brain,
        run_order=MetricOrder(composition.metric.spec),
        run_task_render=SimpleNamespace(loss_context=None),
        model_type_setting=MODEL_TYPE,
        trial_allowed=True,
        scope_is_partial=False,
        resolved_data_scope=[0],
        expert_advice_str="",
        config_manual_data={},
        model_description="",
        max_rounds=1,
        trial_vram_budget=None,
        formal_vram_budget=None,
        trial_time_budget=None,
        formal_time_budget=None,
        run_metric=composition.metric,
        run_scientific_gate_ids=frozenset(),
        planner_strategy_identity=None,
        custom_loss_inventory=None,
    )
    planning._request_attempt_plan(
        bindings,
        identity=AttemptIdentity(round_index=1, attempt_in_round=1, is_formal_round=False),
        total_attempts=0,
        attempts_this_round=0,
        formal_trial_winner=None,
    )
    return brain.plan.call_args.kwargs["metric_spec"]


def test_planner_request_names_the_effective_metric(compose, tmp_path):
    """Defect: the planner is told to minimise MSE while selection maximises utility.

    The planner prompt's direction words and metric identity come from the
    ``metric_spec`` it receives. Passing ``run_metric.spec`` under a formula
    sends ``masked_mse``/lower. A plain run keeps the source spec.
    """
    composition = compose()
    spec = _planner_metric_spec(_tuner_input(tmp_path, composition), composition)
    assert spec.id == _effective_id(composition) and spec.direction == "higher"

    plain = compose(None)
    plain_spec = _planner_metric_spec(_tuner_input(tmp_path, plain), plain)
    assert plain_spec == plain.metric.spec


# --------------------------------------------------------------------------
# HyperparamTuningAgent.run: admission and the run's one order authority
# --------------------------------------------------------------------------


@pytest.fixture
def effect_spies(monkeypatch) -> list[str]:
    """Record and stop at every effect owner ``run()`` may reach first."""
    calls: list[str] = []

    def _owner(name: str):
        def _stop(*_args: Any, **_kwargs: Any) -> Any:
            calls.append(name)
            raise _StopBeforeEffects(name)

        return _stop

    monkeypatch.setattr(tuner, "get_or_create", _owner("hardware"))
    monkeypatch.setattr(tuner, "build_run_invariants", _owner("run_invariants"))
    return calls


def _agent(calls: list[str]):
    def _factory(name: str):
        def _build(**_kwargs: Any) -> Any:
            calls.append(name)
            raise _StopBeforeEffects(name)

        return _build

    return tuner.HyperparamTuningAgent(
        bridge_factory=_factory("llm_bridge"), sandbox_factory=_factory("sandbox")
    )


def test_run_refuses_source_unit_penalty_under_formula_before_effects(
    compose, tmp_path, effect_spies
):
    """Defect: a formula run starts with a penalty stated in source units.

    ``degenerate_penalty_score`` is a score value. Under a formula the score is
    utility, so the operator must name the effective metric in
    ``score_units_metric``. Without the entry-point admission the run continues
    (the effective order is higher, so the direction rule accepts -5.0) and
    reaches its first effect owner instead of refusing with the effective id.
    """
    composition = compose()
    agent_input = _tuner_input(tmp_path, composition, degenerate_penalty_score=-5.0)
    workspace = Path(agent_input.storage.local.workspace)
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        with pytest.raises(ValueError) as error:
            _agent(effect_spies).run(agent_input)

    assert (
        "score_units_metric for degenerate_penalty_score must explicitly name effective "
        f"metric {_effective_id(composition)!r}"
    ) in str(error.value)
    assert effect_spies == []
    assert list(workspace.iterdir()) == []


def test_run_orders_formula_candidates_by_utility(compose, tmp_path, monkeypatch, effect_spies):
    """Defect: the tuner ranks formula candidates by the source metric.

    ``run()`` builds the run's one ``MetricOrder``; every winner, best track,
    skip/bypass gate and penalty rule reads it. The first consumer is the
    penalty-direction rule, so this test observes the real order there and
    stops before effects. Under the formula the order is higher: the -5.0
    penalty is accepted, and the trial-winner rule picks candidate A (utility
    0.8, mse 0.2) over B (utility 0.675, mse 0.1). Built from the source spec,
    the order is lower: the penalty is refused and B would win.

    The plain composition is the parity witness: with no evaluation the same
    penalty is still refused under the source's lower direction.
    """
    seen: list[MetricOrder] = []
    real_rule = tuner._validate_penalty_for_direction

    def _observe(agent_input: Any, order: MetricOrder) -> None:
        seen.append(order)
        real_rule(agent_input, order)
        raise _StopBeforeEffects("order observed")

    monkeypatch.setattr(tuner, "_validate_penalty_for_direction", _observe)

    composition = compose()
    agent_input = _tuner_input(
        tmp_path,
        composition,
        degenerate_penalty_score=-5.0,
        score_units_metric=_effective_id(composition),
    )
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        with pytest.raises(_StopBeforeEffects, match="order observed"):
            _agent(effect_spies).run(agent_input)
    assert effect_spies == []

    def candidate(mse: float, mae: float) -> dict[str, Any]:
        results = _child_results(composition, mse=mse, mae=mae)
        return {
            "status": "success",
            "is_trial": True,
            "health_gate_enabled": False,
            "denoising_score": results["denoising_score"],
            "mse": mse,
        }

    history = [candidate(0.2, 2.0), candidate(0.1, 10.0)]
    winner = policy._best_trial_winner(history, order=seen[0])
    assert winner is not None and winner["mse"] == 0.2

    plain = compose(None)
    with bind_run_task_composition(plain, physical_data_root=str(tmp_path)):
        with pytest.raises(ValueError, match="'lower'-is-better golden metric"):
            _agent(effect_spies).run(_tuner_input(tmp_path, plain, degenerate_penalty_score=-5.0))
    assert effect_spies == []
