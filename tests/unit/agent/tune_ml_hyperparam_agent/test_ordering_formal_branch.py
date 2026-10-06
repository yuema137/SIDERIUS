"""Ordering survives the FORMAL branch, not just the trial branch.

The V19 PR 2 Gate 2 smoke only ever executed trial rounds — every
trained model collapsed and the survivors were skipped on time risk —
so the formal path was never observed live. A code-path audit
(pr2_data_ordering.md §P2-V2) established that trial and formal share
the entire ordering path: divergence is limited to
``_resolve_sample_set_cfg`` (five SAMPLING keys, no ordering),
resolution is mode-independent, and both modes share one
``TrialConfig``, one ``active_params``, one ``training_skill``
dispatch, and one stamp site placed OUTSIDE the trial-only provenance
block.

These tests close the coverage gap that audit exposed. They drive the
real per-round assembly — ``resolve_ordering``, ``TrialConfig``
construction, and ``active_params`` assembly all run for real. Only the
skill EXECUTION is mocked (the established ``_run_skill`` seam), which
sits downstream of everything under test.

Formal mode is reached the production way: ``agent_input.is_trial=True``
makes ``trial_allowed`` true, and a plan with ``is_trial=False`` then
selects ``mode="formal"``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.scoring_stubs import stub_scoring
from workflows.task_composition import (
    bind_run_task_composition,
    build_task_composition_ref,
    compose_run_task_bindings,
)

from .test_tuning_agent import (
    FAKE_REFLECT_RESPONSE,
    _mock_run_skill,
    _synth_reference,
)

# A full permutation of the Quickstart scope, deliberately NOT ascending: an
# ascending order would make a sorting bug invisible.
PERMUTATION = [3, 1, 0, 2]
QUICKSTART_MANIFEST = (
    Path(__file__).resolve().parents[4] / "configs" / "task_composition" / "quickstart.yaml"
)

# is_trial=False is what selects formal mode once trial_allowed is true.
FORMAL_PLAN_RESPONSE = {
    "model_type": "quickstart_reference_mlp",
    "hypothesis": "Formal round with a forced sequential ordering.",
    "reasoning": "Exercise the formal branch.",
    "model_config": {"hidden_dim": 16, "segmentation_size": 4, "batch_size": 1},
    "train_config": {"epochs": 1, "lr": 1e-4},
    "loss_config": {"loss_type": "ce", "reduction": "mean"},
    "is_trial": False,
}


@pytest.fixture
def formal_round(tmp_path):
    """Run one FORMAL round with a forced sequential ordering.

    Returns ``(captured_params, saved_records)`` — the kwargs handed to
    ``training_skill`` and the records the tuner persisted.
    """
    captured: list[dict] = []

    def _capturing_run_skill(skill_folder, sandbox, **params):
        if skill_folder == "training_skill":
            captured.append(dict(params))
        return _mock_run_skill(skill_folder, sandbox, **params)

    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
        patch(
            "nodes.ml_hyperparameter_tune_agent.runtime._run_skill",
            side_effect=_capturing_run_skill,
        ),
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_synth_reference(),
        ),
        tempfile.TemporaryDirectory() as configs_dir,
    ):
        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = FORMAL_PLAN_RESPONSE
        mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE

        saved_records: list[dict] = []
        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
        mock_sandbox.save_record.side_effect = lambda r: saved_records.append(r)
        data_dir = tmp_path / "quickstart_data"
        data_dir.mkdir(exist_ok=True)
        deliverable_dir = tmp_path / "deliverables"
        deliverable_dir.mkdir(exist_ok=True)
        mock_sandbox.base_dir = str(deliverable_dir)
        mock_sandbox.dirs = {
            "configs": configs_dir,
            "data": str(data_dir),
            "denoised": str(deliverable_dir),
        }
        # The multi-file scoring path (`file_vector, scalar = score_vector(...)`)
        # is reached only in trial/formal mode; the legacy single-file tests
        # never hit it, so the shared MagicMock sandbox has no return value for
        # it. The framework-owned Quickstart example has four partitions.
        _fv = [1.75] * 4
        stub_scoring(mock_sandbox, _fv, 1.75)

        composition = compose_run_task_bindings(str(QUICKSTART_MANIFEST))
        agent_input = HyperparamTuningInput(
            planner_strategy="native-timing-v1",
            model_type="quickstart_reference_mlp",
            run_name="formal_ordering_test",
            max_rounds=1,
            attempts_per_round=1,
            attempts_per_formal_round=1,
            max_fail_rounds=1,
            # trial_allowed=True; the plan's is_trial=False then selects formal.
            is_trial=True,
            # Quickstart declares four partitions, so PERMUTATION covers the
            # complete task domain without inventing task-specific subset syntax.
            health_gate_enabled=False,
            order_strategy_override="sequential",
            file_order_override=PERMUTATION,
            task_composition_ref=build_task_composition_ref(composition),
            llm_provider="gemini",
            llm_model_id="test-model",
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="formal_ordering_test"),
            ),
            progress_bar=False,
        )
        with bind_run_task_composition(composition, physical_data_root=str(data_dir)):
            HyperparamTuningAgent().run(agent_input)

    assert captured, "training_skill was never dispatched"
    assert saved_records, "no record was persisted"
    return captured[0], saved_records


def _formal_record(saved_records: list[dict]) -> ExperimentRecord:
    """The persisted formal record, read the way production reads it.

    The raw dict handed to ``save_record`` does NOT carry ``is_trial`` for a
    formal round — that key is written only inside the trial-only provenance
    block, and ``False`` arrives via the schema default. So the record is
    validated through ``ExperimentRecord`` here, exactly as the tuner does
    before saving and as every downstream consumer does when reading. That
    also makes these assertions about what consumers actually see.
    """
    records = [ExperimentRecord.model_validate(r) for r in saved_records]
    formal = [r for r in records if r.is_trial is False and r.status == "success"]
    assert formal, (
        f"no successful formal record persisted; "
        f"statuses={[(r.status, r.is_trial) for r in records]}"
    )
    return formal[0]


# ---- dispatch parameters ----


def test_formal_round_dispatches_the_resolved_sequential_ordering(formal_round):
    """Requirements 1-4: formal mode selected, sequential resolved, exact
    permutation preserved, and the same values reach training_skill."""
    params, saved_records = formal_round

    # 1. the round really was formal — asserted on the persisted record,
    #    which is what mode="formal" produces.
    assert _formal_record(saved_records).is_trial is False

    # 2 + 3 + 4. the resolved values reach the dispatch unchanged.
    assert params["order_strategy"] == "sequential"
    assert params["file_order"] == PERMUTATION


def test_formal_dispatch_carries_no_proposal_or_override_material(formal_round):
    """The skill boundary takes resolved values ONLY — it cannot re-derive
    precedence, by construction."""
    params, _ = formal_round
    assert "order_strategy_override" not in params
    assert "file_order_override" not in params
    assert "proposed_order_strategy" not in params


# ---- persisted provenance ----


def test_formal_record_carries_the_full_ordering_provenance(formal_round):
    """Requirement 5: the formal record stamps resolved values and source."""
    _params, saved_records = formal_round
    record = _formal_record(saved_records)

    assert record.resolved_order_strategy == "sequential"
    assert record.resolved_file_order == PERMUTATION
    assert record.ordering_resolution_source == "operator_override"
    assert record.override_order_strategy == "sequential"
    assert record.override_file_order == PERMUTATION


def test_ordering_stamp_is_not_gated_by_is_trial(formal_round):
    """Requirement 6: the stamp is present precisely BECAUSE it sits outside
    the trial-only provenance block. This is the assertion that would fail if
    someone moved it inside `if trial_config.is_trial:`."""
    _params, saved_records = formal_round
    record = _formal_record(saved_records)

    assert record.is_trial is False, "precondition: this must be a formal record"
    assert record.resolved_order_strategy is not None, (
        "formal record lost its ordering stamp — the stamp has probably been "
        "moved inside the trial-only provenance block"
    )
    # The trial-only fields are absent, proving the stamp came from the
    # unconditional block rather than the trial branch.
    assert record.trial_strategy is None


def test_dispatch_and_record_agree(formal_round):
    """What was dispatched is what was recorded — no drift between the two."""
    params, saved_records = formal_round
    record = _formal_record(saved_records)

    assert params["order_strategy"] == record.resolved_order_strategy
    assert params["file_order"] == record.resolved_file_order
