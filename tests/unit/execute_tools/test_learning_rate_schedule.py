"""Explicit schedules, actual CPU execution, and disabled compatibility."""

import pytest
import torch
from pydantic import ValidationError
from torch.utils.data import DataLoader

from execute_tools.dataset_config import bind_dataset_profile
from execute_tools.learning_rate_schedule import build_epoch_lr_controller
from execute_tools.task_data_path import EvalMaterializationParams, bind_task_data_path
from execute_tools.train_engine_sandbox import (
    build_training_optimizer,
    run_experiment,
    run_experiment_streaming,
)
from ml_models.models_format_sandbox import LossConfig, TrainConfig
from tests.helpers.synthetic_training_data_path import TwoFamilyDataPath
from tests.helpers.two_family_profile import write_two_family_fixture
from tests.unit.execute_tools.test_step07a_c1_validation_pass import (
    _sandbox,
    _seed_everything,
    _tiny_model_cfg,
)


@pytest.mark.parametrize(
    "schedule",
    [
        {"kind": "cosine", "horizon_epochs": 0, "min_lr": 0},
        {"kind": "cosine", "horizon_epochs": True, "min_lr": 0},
        {"kind": "cosine", "horizon_epochs": 1.5, "min_lr": 0},
        {"kind": "cosine", "horizon_epochs": 2, "min_lr": float("nan")},
        {"kind": "cosine", "horizon_epochs": 2, "min_lr": 0.1},
        {"kind": "step", "step_size_epochs": 1, "gamma": 0},
        {"kind": "step", "step_size_epochs": 1, "gamma": float("inf")},
        {"kind": "step", "step_size_epochs": 1, "gamma": 1.1},
        {"kind": "step", "step_size_epochs": 1},
        {"kind": "step", "step_size_epochs": 1, "gamma": 0.5, "unused": 3},
    ],
)
def test_invalid_schedule_rejected(schedule):
    with pytest.raises(ValidationError):
        TrainConfig(lr=0.01, lr_schedule=schedule)


def test_disabled_serialization_and_optimizer_are_untouched():
    cfg = TrainConfig()
    assert "lr_schedule" not in cfg.model_dump()
    assert cfg.model_dump_json() == TrainConfig(lr_schedule=None).model_dump_json()
    optimizer = build_training_optimizer(torch.nn.Linear(2, 1), cfg)
    before = optimizer.state_dict()
    assert build_epoch_lr_controller(optimizer, None) is None
    assert optimizer.state_dict() == before


def test_invalid_second_group_does_not_mutate_first():
    model = torch.nn.Linear(2, 1)
    optimizer = torch.optim.SGD(
        [{"params": [model.weight], "lr": 0.1}, {"params": [model.bias], "lr": 0.001}]
    )
    cfg = TrainConfig(lr=0.1, lr_schedule={"kind": "cosine", "horizon_epochs": 2, "min_lr": 0.01})
    with pytest.raises(ValueError, match="min_lr"):
        build_epoch_lr_controller(optimizer, cfg.lr_schedule)
    assert [group["lr"] for group in optimizer.param_groups] == [0.1, 0.001]


@pytest.mark.parametrize(
    "kind,expected",
    [("cosine", [0.01, 0.0055, 0.001, 0.001]), ("step", [0.01, 0.005, 0.0025, 0.00125])],
)
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.usefixtures("synthetic_task_config")
def test_actual_cpu_paths_record_completed_epoch_rates(
    tmp_path, monkeypatch, streaming, kind, expected
):
    import execute_tools.train_engine_sandbox as engine

    observed_rates = []
    factory = engine.build_training_optimizer

    def recording_optimizer(*args, **kwargs):
        optimizer = factory(*args, **kwargs)
        real_step = optimizer.step

        def step(*step_args, **step_kwargs):
            observed_rates.append([float(group["lr"]) for group in optimizer.param_groups])
            return real_step(*step_args, **step_kwargs)

        optimizer.step = step
        return optimizer

    monkeypatch.setattr(engine, "build_training_optimizer", recording_optimizer)
    fx = write_two_family_fixture(tmp_path)
    data_path = TwoFamilyDataPath(fx)
    schedule = (
        {"kind": "cosine", "horizon_epochs": 2, "min_lr": 0.001}
        if kind == "cosine"
        else {"kind": "step", "step_size_epochs": 1, "gamma": 0.5}
    )
    cfg = TrainConfig(lr=0.01, epochs=4, batch_size=2, device="cpu", lr_schedule=schedule)
    from agent.schemas.hyperparam_tuning import ExperimentPlan
    from core.sandbox_executor import TidmadSandbox
    from execute_tools.training_history import interpret_training_results

    plan = ExperimentPlan.model_validate(
        {
            "model_type": "wavenet",
            "hypothesis": "schedule",
            "reasoning": "test",
            "is_trial": True,
            "model_config": _tiny_model_cfg(fx.seg_size).model_dump(),
            "train_config": cfg.model_dump(),
            "loss_config": LossConfig().model_dump(),
        }
    )
    _, executed_train, _ = TidmadSandbox.__new__(TidmadSandbox)._validate_configs(
        plan.model_type, plan.model_cfg, plan.train_cfg, plan.loss_cfg, "run", "run"
    )
    cfg = TrainConfig.model_validate(executed_train)
    assert cfg.lr_schedule.model_dump() == schedule
    _seed_everything()
    with bind_dataset_profile(fx.profile), bind_task_data_path(data_path):
        if streaming:
            result = run_experiment_streaming(
                _tiny_model_cfg(fx.seg_size),
                cfg,
                LossConfig(),
                sample_set=fx.full_sample_set(),
                data_dir=fx.data_dir,
                sandbox_dirs=_sandbox(tmp_path, "run"),
                exp_id="run",
                train_base_seed=123,
                profile=fx.profile,
                **data_path.scope_kwargs(fx.full_sample_set(), None),
            )
        else:
            dataset = data_path.validation_dataset(
                data_path.scope({"0": list(range(fx.segments_per_file))}),
                EvalMaterializationParams(data_dir=fx.data_dir),
            )
            result = run_experiment(
                _tiny_model_cfg(fx.seg_size),
                cfg,
                LossConfig(),
                DataLoader(dataset, batch_size=2, drop_last=True),
                _sandbox(tmp_path, "run"),
                "run",
            )
    assert result is not None
    assert interpret_training_results(result, expected_validation=False).history is not None
    history = result["training_history"]
    assert history["epochs_completed"] == 4
    assert [row[0] for row in history["learning_rates"]] == pytest.approx(expected)
    assert observed_rates and len(observed_rates) % 4 == 0
    steps_per_epoch = len(observed_rates) // 4
    assert [row[0] for row in observed_rates] == pytest.approx(
        [rate for rate in expected for _ in range(steps_per_epoch)]
    )


def test_requested_effective_schedule_and_partial_parent_lock(tmp_path):
    from agent.schemas.parameter_rules import (
        ParameterRuleError,
        ParameterRules,
        apply_parameter_rules,
    )
    from tests.unit.agent.schemas.test_parameter_rules import _plan

    requested = _plan()
    requested.train_cfg["lr_schedule"] = {"kind": "step", "step_size_epochs": 2, "gamma": 0.5}
    effective = apply_parameter_rules(
        requested,
        workflow_rules=ParameterRules.model_validate({"train_config.lr_schedule": {"exact": None}}),
    )
    assert requested.train_cfg["lr_schedule"]["gamma"] == 0.5
    effective_cfg = TrainConfig.model_validate(effective.train_cfg)
    assert effective_cfg.lr_schedule is None
    from tests.unit.execute_tools.test_step07a_c1_validation_pass import _run

    executed = _run(
        write_two_family_fixture(tmp_path),
        tmp_path,
        name="locked",
        eval_sample_set=None,
        epochs=1,
        lr_schedule=effective_cfg.lr_schedule,
    )
    assert "learning_rates" not in executed["training_history"]
    partial = ParameterRules.model_validate({"train_config.lr_schedule.gamma": {"exact": 0.25}})
    locked = apply_parameter_rules(requested, workflow_rules=partial)
    assert TrainConfig.model_validate(locked.train_cfg).lr_schedule.gamma == 0.25
    with pytest.raises(ParameterRuleError, match="lr_schedule"):
        apply_parameter_rules(_plan(), workflow_rules=partial)


def test_epoch_zero_matches_shared_optimizer_factory_and_multiple_groups():
    model = torch.nn.Linear(2, 1)
    optimizer = torch.optim.SGD(
        [{"params": [model.weight], "lr": 0.01}, {"params": [model.bias], "lr": 0.02}]
    )
    cfg = TrainConfig(lr_schedule={"kind": "step", "step_size_epochs": 2, "gamma": 0.5})
    controller = build_epoch_lr_controller(optimizer, cfg.lr_schedule)
    assert controller.start_epoch(0) == [0.01, 0.02]
    assert controller.start_epoch(1) == [0.01, 0.02]
    assert controller.start_epoch(2) == [0.005, 0.01]
    assert controller.start_epoch(100) == pytest.approx([0.01 * 0.5**50, 0.02 * 0.5**50])
    probe = build_training_optimizer(model, cfg)
    assert probe.param_groups[0]["lr"] == cfg.lr


def test_history_rejects_incomplete_or_invalid_rate_rows():
    from execute_tools.train_engine_sandbox import _build_training_history

    history = _build_training_history(
        loss_cfg=LossConfig(),
        epochs_planned=2,
        train_objective=[1.0, 0.5],
        validation_objective=None,
        validation_requested_samples=None,
        validation_samples=None,
        validation_seconds=None,
    )
    assert "learning_rates" not in history.model_dump()
    for rates in ([[0.01]], [[], []], [[0.01], [float("nan")]], [[0.01], [0.01, 0.02]]):
        with pytest.raises(ValidationError):
            type(history).model_validate({**history.model_dump(), "learning_rates": rates})


@pytest.mark.parametrize("streaming", [False, True])
def test_scheduled_zero_step_attempt_does_not_publish_history(tmp_path, streaming):
    from execute_tools.task_data_path import TrainingScopeError
    from tests.unit.execute_tools.test_failure_honesty_zero_optimizer_steps import (
        PAIR_PROFILE,
        _cfg,
        _Pairs,
        _PairTaskDataPath,
        _sandbox_dirs,
        _train_cfg,
    )

    cfg = _train_cfg(batch_size=8).model_copy(
        update={
            "lr_schedule": TrainConfig(
                lr_schedule={"kind": "step", "step_size_epochs": 1, "gamma": 0.5}
            ).lr_schedule
        }
    )
    dirs = _sandbox_dirs(tmp_path)
    with bind_task_data_path(_PairTaskDataPath()), pytest.raises(TrainingScopeError):
        if streaming:
            run_experiment_streaming(
                _cfg(),
                cfg,
                LossConfig(),
                sample_set={},
                task_scope=list(range(6)),
                data_dir=str(tmp_path),
                sandbox_dirs=dirs,
                exp_id="empty",
                train_base_seed=42,
                profile=PAIR_PROFILE,
            )
        else:
            run_experiment(
                _cfg(),
                cfg,
                LossConfig(),
                DataLoader(_Pairs(6), batch_size=8, drop_last=True),
                dirs,
                "empty",
            )
    from pathlib import Path

    assert not list(Path(dirs["models"]).iterdir())
    assert not list(Path(dirs["results"]).iterdir())


def test_disabled_matches_constant_rate_real_optimizer_trajectory(tmp_path):
    from tests.unit.execute_tools.test_step07a_c1_validation_pass import (
        _run,
        _saved_state,
        _states_equal,
    )

    fixture = write_two_family_fixture(tmp_path)
    disabled = _run(fixture, tmp_path, name="disabled", eval_sample_set=None, epochs=2)
    constant = _run(
        fixture,
        tmp_path,
        name="constant",
        eval_sample_set=None,
        epochs=2,
        lr_schedule={"kind": "step", "step_size_epochs": 1, "gamma": 1.0},
    )
    assert _states_equal(_saved_state(tmp_path, "disabled"), _saved_state(tmp_path, "constant"))
    assert disabled["loss_history"] == constant["loss_history"]
    executed = constant["training_history"].copy()
    assert executed.pop("learning_rates") == [[0.001], [0.001]]
    assert disabled["training_history"] == executed


def test_public_config_manual_exposes_explicit_schedule_strategies():
    from agent.skills.check_config_format_skill.wrapper import run_skill

    result = run_skill(None)
    assert result["status"] == "success"
    schema = result["data"]["schemas"]["TrainConfig"]
    field = schema["properties"]["lr_schedule"]
    assert field["default"] is None
    variants = field["anyOf"][0]["discriminator"]["mapping"]
    assert set(variants) == {"cosine", "step"}
    assert set(schema["$defs"]["CosineLearningRateSchedule"]["required"]) == {
        "kind",
        "horizon_epochs",
        "min_lr",
    }
    assert set(schema["$defs"]["StepLearningRateSchedule"]["required"]) == {
        "kind",
        "step_size_epochs",
        "gamma",
    }
