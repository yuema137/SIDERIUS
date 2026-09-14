"""Step-00 PB-1 (planner) + PB-2 (reflector) prompt goldens.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.1 / §22 OD-1.

These baselines capture the final ordered ``(system_prompt, user_prompt)``
pair at the true LLM request boundary (the last deterministic point before
``client.chat.completions.create`` — design §4.1), produced by the REAL
``LLMBridge.plan()`` / ``LLMBridge.reflect()`` render bodies. Capture is via
``BoundaryRecorderBridge``, which overrides only the three create-owning
methods, so a change to the RENDER (not merely to the arguments) fails these
goldens — §10.1's validation consequence.

OD-1 (operator-approved 2026-08-12): the planner golden uses a
deterministic <=3-record history so the condensed-history branch
(`_truncate_memory_history`, byte-unstable across processes via frozenset
iteration when len > 3) never runs. The >3 branch is an explicit deferral;
``test_pb1_full_window_boundary_is_the_deferral_line`` records that
boundary mechanically. PYTHONHASHSEED pinning is rejected.

Fixture rules (design §13.1): every source-embedding input
(``plugin_source_excerpt``, ``model_description``, ``config_manual``, ...)
is a TEST-OWNED frozen value — no production source text is embedded in the
goldens. ``registry=None`` keeps the auto-mode render free of live-registry
coupling; the ``force_model="punet"`` variant deliberately pins the LIVE
builtin output-type registry (production truth: punet is a classifier).

Goldens: ``goldens/`` sibling directory. Captured at clean tree by the 0A
capture commit; regeneration only per §17 rule 3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.prompts import (
    _PLANNER_HIDDEN_RECORD_KEYS,
    _planner_visible,
    _truncate_memory_history,
)
from agent.schemas.training_diagnosis import TrainingDiagnosis
from tests.helpers.golden import assert_golden
from tests.helpers.llm_boundary_recorder import (
    BoundaryRecorderBridge,
    NetworkEscapeError,
)
from tests.helpers.metric_fixtures import shipped_spec

GOLDENS = Path(__file__).parent / "goldens"

# ---------------------------------------------------------------------------
# Test-owned frozen fixtures (deterministic; NO production source text)
# ---------------------------------------------------------------------------

_PLUGIN_SOURCE_EXCERPT = (
    "[PLUGIN CONFIG SOURCE EXCERPT]\n"
    "class Step00FixtureConfig(BaseModel):\n"
    "    hidden_dim: int = 32\n"
    "    n_layers: int = 2\n"
    "    # test-owned frozen class; NOT production source (design §13.1)\n"
)

_SCORE_TABLE_MD = "| model | score |\n|---|---|\n| **step00_fixture** | **-2.9100** |\n"

_TASK_DESCRIPTION = (
    "Step-00 fixture task: denoise a synthetic 1-D int8 time series into "
    "256-class per-timestep logits."
)

_HISTORY_3 = [
    {
        "exp_id": "punet_step00_fixture_001",
        "status": "success",
        "model_type": "punet",
        "denoising_score": -2.91,
        "is_trial": True,
        "params": {
            "model_config": {"hidden_dim": 32, "depth": 2},
            "train_config": {"lr": 0.0005, "batch_size": 8, "epochs": 1},
            "loss_config": {"loss_type": "ce"},
        },
        "memory": {
            "hypothesis": "A small punet converges within one epoch.",
            "conclusion": "Trial score -2.91; stable loss curve.",
            "round_index": 1,
            "memory_update": "hidden_dim 32 is a safe floor.",
        },
    },
    {
        "exp_id": "punet_step00_fixture_002",
        "status": "skipped_oom_risk",
        "model_type": "punet",
        "denoising_score": None,
        "is_trial": True,
        "params": {
            "model_config": {"hidden_dim": 256, "depth": 6},
            "train_config": {"lr": 0.0005, "batch_size": 32, "epochs": 1},
            "loss_config": {"loss_type": "focal"},
        },
        "memory": {
            "hypothesis": "A much wider punet improves the score.",
            "conclusion": "Rejected by the VRAM gate before training.",
            "round_index": 2,
            "memory_update": "Reduce batch_size from 32 to 8.",
        },
    },
    {
        "exp_id": "punet_step00_fixture_003",
        "status": "success",
        "model_type": "punet",
        "denoising_score": -2.55,
        "is_trial": False,
        # Step 07 PR 07b — a real 07a payload on ONE window record. It does two
        # jobs at once: PB-1 now pins a RENDERED dynamics line (not only the
        # "none recorded" path), and the JSON history block above it must stay
        # byte-identical, which is the hidden-key contract proved on a golden
        # rather than only in a boundary test.
        "training_history": {"objective_kind": "focal"},
        "training_diagnosis": {
            "state": "ok",
            "validation_state": "present",
            "comparability": "established",
            "epochs_planned": 1,
            "epochs_completed": 1,
            "truncated": False,
            "train_first": 0.0189,
            "train_last": 0.0123,
            "train_min": 0.0123,
            "train_min_epoch": 0,
            "validation_first": 0.0201,
            "validation_last": 0.0155,
            "validation_min": 0.0155,
            "best_validation_epoch": 0,
            "final_vs_best_validation_degradation": 0.0,
            "final_vs_best_validation_degradation_rel": 0.0,
            "validation_degraded_after_best": False,
            "train_validation_gap_final": 0.0032,
            "train_validation_gap_final_rel": 0.26,
            "train_trend": "decreasing",
            "validation_trend": "decreasing",
            "flat_rel_tol": 0.01,
        },
        "params": {
            "model_config": {"hidden_dim": 64, "depth": 3},
            "train_config": {"lr": 0.0005, "batch_size": 8, "epochs": 1},
            "loss_config": {"loss_type": "focal"},
        },
        "memory": {
            "hypothesis": "Moderate width with focal loss beats the trial.",
            "conclusion": "Formal score -2.55; new best.",
            "round_index": 3,
            "memory_update": "Focal loss outperforms ce at hidden_dim 64.",
        },
    },
]


#: The SHIPPED TIDMAD task render (Step 07 PR 07b, P2). Built from the same
#: authorities production uses — the shipped dataset, the shipped Model-I/O
#: contract, the shipped health config, the shipped registry — so the goldens
#: below remain a production-truth pin rather than a fixture of literals. If a
#: rendered token's authority changes, these goldens fail as production drift,
#: which is exactly what they are for.
def tidmad_task_render():
    from agent.prompt_templates.tuner.rendering import (
        EFFICIENCY_BAND_FRACTION,
        build_tuner_task_render,
    )
    from execute_tools.dataset_config import TIDMAD
    from execute_tools.health_checks.config import load_health_gates_config
    from workflows.task_config import run_bound_model_io_contract

    return build_tuner_task_render(
        dataset=TIDMAD,
        model_io_contract=run_bound_model_io_contract(),
        health_config=load_health_gates_config(),
        efficiency_band_fraction=EFFICIENCY_BAND_FRACTION,
    )


def planner_fixture_kwargs(force_model: str = "auto") -> dict:
    """The full ``plan()`` surface, every value pinned.

    Passing EVERY parameter explicitly keeps the golden independent of
    default drift and doubles as documentation of the surface WF-1 pins.
    """
    return dict(
        memory_history=_HISTORY_3,
        expert_advice="Prefer focal-family losses; keep epochs at 1.",
        force_model=force_model,
        config_manual={"hidden_dim": {"min": 8, "max": 512}},
        model_description="Fixture description: a U-Net-style 1-D denoiser.",
        exploration_checklist="[EXPLORATION CHECKLIST]\n- hidden_dim: tried 32, 64, 256",
        plugin_source_excerpt=_PLUGIN_SOURCE_EXCERPT,
        current_round=2,
        max_rounds=5,
        trial_allowed=True,
        force_formal_round=True,
        plan_overrides={"trial_portion": 0.05},
        max_epochs=1,
        resolved_data_scope=[4, 5, 6],
        trial_vram_budget_gb=8.0,
        formal_vram_budget_gb=24.0,
        trial_time_budget_minutes=20.0,
        formal_time_budget_minutes=120.0,
        last_vram_estimate_gb=3.2,
        last_time_estimate_minutes=6.5,
        last_batch_size=8,
        last_mode="trial",
        score_table_md=_SCORE_TABLE_MD,
        task_description=_TASK_DESCRIPTION,
        custom_loss_inventory=None,
        task_render=tidmad_task_render(),
        metric_spec=shipped_spec(),
    )


_REFLECT_ACTUAL_RESULTS = {
    "denoising_score": -2.55,
    "final_loss": 0.0123,
    "params": {
        "model_config": {"hidden_dim": 64, "depth": 3},
        "train_config": {"lr": 0.0005, "batch_size": 8, "epochs": 1},
        "loss_config": {"loss_type": "focal"},
    },
    "status": "success",
}

_REFLECT_CONTEXT = {
    "baseline_score": -2.98,
    "best_score_so_far": -2.91,
    "is_new_best": True,
    "rank": 1,
    "total_experiments": 3,
    "best_config_so_far": {"model_config": {"hidden_dim": 32, "depth": 2}},
    "best_same_loss_final_loss": None,
    "current_loss_type": "focal",
    "baseline_params": 1_200_000,
    "baseline_epochs": 1,
    "current_params": 850_000,
    "current_epochs": 1,
    "params_ratio": 0.71,
    "epochs_ratio": 1.0,
    "is_more_efficient": True,
    "training_psd_segments": 200,
    "eval_psd_segments": 40,
    "baseline_psd_segments": 4000,
    "trial_portion": 0.05,
    "eval_portion": 0.1,
    "score_comparison_table": _SCORE_TABLE_MD,
}


def reflect_fixture_args() -> tuple:
    return (
        "punet_step00_fixture_003",
        "Moderate width with focal loss beats the trial.",
        _REFLECT_ACTUAL_RESULTS,
        _REFLECT_CONTEXT,
    )


#: Step 07 PR 07b — the reflector's two ADDITIVE kwargs. The diagnosis is the
#: 07a shape a real round produces, so PB-2 pins a rendered dynamics block
#: rather than an empty one.
_REFLECT_DIAGNOSIS = TrainingDiagnosis(
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


def reflect_fixture_kwargs() -> dict:
    return {
        "metric_spec": shipped_spec(),
        "training_diagnosis": _REFLECT_DIAGNOSIS,
    }


# ---------------------------------------------------------------------------
# PB-2 reflector
# ---------------------------------------------------------------------------


class TestPB2Reflector:
    def test_reflector_render(self):
        bridge = BoundaryRecorderBridge()
        out = bridge.reflect(*reflect_fixture_args(), **reflect_fixture_kwargs())
        assert out == {}
        assert len(bridge.captures) == 1
        method, label, system, user = bridge.captures[0]
        assert method == "_chat_json"
        assert label == "tuner.reflector"
        assert_golden(
            system, GOLDENS / "pb2_reflector_system.txt", surface="PB-2 reflector system prompt"
        )
        assert_golden(
            user, GOLDENS / "pb2_reflector_user.txt", surface="PB-2 reflector user prompt"
        )


# ---------------------------------------------------------------------------
# Capture-mechanism guarantees (0A acceptance criteria)
# ---------------------------------------------------------------------------


class TestBoundaryRecorderGuarantees:
    def test_no_network_guard_raises_on_client_access(self):
        """Affirmative offline guard (design §14, review F14): any path that
        escapes the recorder overrides and touches the client object fails
        loudly instead of issuing a billable call."""
        bridge = BoundaryRecorderBridge()
        with pytest.raises(NetworkEscapeError):
            _ = bridge.client.chat

    def test_generate_is_pass_through_at_the_boundary(self):
        """0A acceptance: the REAL ``generate`` body runs and the pair
        recorded at the ``_chat_json`` boundary is byte-identical to the
        method-entry arguments — proving §4.1's pass-through claim on the
        implementation, not just the audit."""
        bridge = BoundaryRecorderBridge()
        bridge.generate("SYSTEM-BYTES", "USER-BYTES", label="step00.check")
        assert bridge.captures == [("_chat_json", "step00.check", "SYSTEM-BYTES", "USER-BYTES")]
