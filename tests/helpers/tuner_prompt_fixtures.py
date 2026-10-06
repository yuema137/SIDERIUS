"""Task-neutral fixtures for tuner prompt boundary tests."""

from __future__ import annotations

from agent.prompt_templates.tuner.rendering import TunerTaskRender
from agent.schemas.training_diagnosis import TrainingDiagnosis
from execute_tools.evaluation_metric import MetricSpec
from tests.helpers.metric_fixtures import accuracy_like_spec

DIAGNOSIS = TrainingDiagnosis(
    state="ok",
    validation_state="present",
    comparability="established",
    epochs_planned=1,
    epochs_completed=1,
    truncated=False,
    train_first=0.0189,
    train_last=0.0123,
    train_min=0.0123,
    train_min_epoch=0,
    validation_first=0.0201,
    validation_last=0.0155,
    validation_min=0.0155,
    best_validation_epoch=0,
    final_vs_best_validation_degradation=0.0,
    final_vs_best_validation_degradation_rel=0.0,
    validation_degraded_after_best=False,
    train_validation_gap_final=0.0032,
    train_validation_gap_final_rel=0.26,
    train_trend="decreasing",
    validation_trend="decreasing",
)

HISTORY = [
    {
        "exp_id": "fixture_001",
        "status": "success",
        "model_type": "fixture_model",
        "denoising_score": 0.4,
        "is_trial": True,
        "params": {"loss_config": {"loss_type": "cross_entropy"}},
        "memory": {"hypothesis": "Try the baseline.", "conclusion": "Completed."},
    },
    {
        "exp_id": "fixture_002",
        "status": "skipped_oom_risk",
        "model_type": "fixture_model",
        "denoising_score": None,
        "is_trial": True,
        "params": {"loss_config": {"loss_type": "cross_entropy"}},
        "memory": {"hypothesis": "Increase width.", "conclusion": "Refused."},
    },
    {
        "exp_id": "fixture_003",
        "status": "success",
        "model_type": "fixture_model",
        "denoising_score": 0.5,
        "is_trial": False,
        "training_history": {"objective_kind": "cross_entropy"},
        "training_diagnosis": DIAGNOSIS.model_dump(mode="json"),
        "params": {"loss_config": {"loss_type": "cross_entropy"}},
        "memory": {"hypothesis": "Use the trial.", "conclusion": "Improved."},
    },
]

TASK_RENDER = TunerTaskRender(
    builtin_model_roster="",
    full_scope_segments=None,
    output_contract_shape=None,
    focal_alpha_default="0.25",
    focal_gamma_default="2",
    gate_check_names=(),
    efficiency_band_pct="5",
    available_models_block="No framework-owned model roster is declared.",
    per_file_table_protocol="",
    score_field_noun="metric",
    target_strategy_impact_note="",
    sampling_impact_tradeoff="",
    per_file_comparison_block="",
    score_display_noun="score",
)


def planner_kwargs(metric_spec: MetricSpec | None = None) -> dict:
    """Return one complete, task-neutral planner call surface."""
    return {
        "planner_strategy": "native-timing-v1",
        "memory_history": HISTORY,
        "expert_advice": "Compare the recorded evidence.",
        "force_model": "auto",
        "config_manual": {"hidden_dim": {"minimum": 8, "maximum": 64}},
        "model_description": "A test-owned supervised model.",
        "exploration_checklist": "",
        "plugin_source_excerpt": "",
        "current_round": 2,
        "max_rounds": 3,
        "trial_allowed": True,
        "force_formal_round": True,
        "plan_overrides": {},
        "max_epochs": 1,
        "resolved_data_scope": [0, 1],
        "trial_vram_budget_gb": 1.0,
        "formal_vram_budget_gb": 2.0,
        "trial_time_budget_minutes": 2.0,
        "formal_time_budget_minutes": 5.0,
        "last_vram_estimate_gb": 0.2,
        "last_time_estimate_minutes": 0.5,
        "last_batch_size": 4,
        "last_mode": "trial",
        "score_table_md": "| model | score |\n|---|---|\n| fixture | 0.5 |",
        "task_description": "A synthetic supervised task.",
        "custom_loss_inventory": None,
        "task_render": TASK_RENDER,
        "metric_spec": metric_spec or accuracy_like_spec("fixture_quality"),
    }


def reflector_args() -> tuple:
    """Return the reflector's positional test inputs."""
    return (
        "fixture_003",
        "Use the trial.",
        {
            "denoising_score": 0.5,
            "final_loss": 0.0123,
            "params": {"loss_config": {"loss_type": "cross_entropy"}},
            "status": "success",
        },
        {
            "baseline_score": 0.3,
            "best_score_so_far": 0.4,
            "is_new_best": True,
            "rank": 1,
            "total_experiments": 3,
            "score_comparison_table": "| model | score |\n|---|---|\n| fixture | 0.5 |",
        },
    )


def reflector_kwargs(metric_spec: MetricSpec | None = None) -> dict:
    """Return the reflector's keyword test inputs."""
    return {
        "metric_spec": metric_spec or accuracy_like_spec("fixture_quality"),
        "training_diagnosis": DIAGNOSIS,
        "task_render": TASK_RENDER,
    }
